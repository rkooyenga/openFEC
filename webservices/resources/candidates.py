import sqlalchemy as sa
from flask_apispec import doc

from webservices import args
from webservices import docs
from webservices import utils
from webservices import schemas
from webservices import exceptions
from webservices.common import models
from webservices.common.views import ApiResource


def filter_multi_fields(model):
    return [
        ('candidate_id', model.candidate_id),
        ('candidate_status', model.candidate_status),
        ('district', model.district),
        ('incumbent_challenge', model.incumbent_challenge),
        ('office', model.office),
        ('party', model.party),
        ('state', model.state),
    ]


# def filter_match_fields(model):
#     return[
#         ('federal_funds_flag', models.CandidateFlags.federal_funds_flag),
#         ('five_thousand_flag', models.CandidateFlags.five_thousand_flag),
#     ]


@doc(
    tags=['candidate'],
    description=docs.CANDIDATE_LIST,
)
class CandidateList(ApiResource):

    model = models.Candidate
    schema = schemas.CandidateSchema
    page_schema = schemas.CandidatePageSchema
    filter_multi_fields = filter_multi_fields(models.Candidate)
    filter_fulltext_fields = [('q', models.CandidateSearch.fulltxt)]
    aliases = {'receipts': models.CandidateSearch.receipts}

    query_options = [
        sa.orm.joinedload(models.Candidate.flags),
    ]

    @property
    def args(self):
        return utils.extend(
            args.paging,
            args.candidate_list,
            args.candidate_detail,
            args.make_sort_args(
                default='name',
                validator=args.IndexValidator(
                    models.Candidate,
                    extra=list(self.aliases.keys()),
                ),
            )
        )

    def build_query(self, **kwargs):
        query = super().build_query(**kwargs)

        if {'receipts', '-receipts'}.intersection(kwargs.get('sort', [])) and 'q' not in kwargs:
            raise exceptions.ApiError(
                'Cannot sort on receipts when parameter "q" is not set',
                status_code=422,
            )

        if 'five_thousand_flag' in kwargs:
            query = query.filter(
                models.Candidate.flags.has(models.CandidateFlags.five_thousand_flag == kwargs['five_thousand_flag'])
            )
        if 'federal_funds_flag' in kwargs:
            query = query.filter(
                models.Candidate.flags.has(models.CandidateFlags.federal_funds_flag == kwargs['federal_funds_flag'])
            )

        if kwargs.get('q'):
            query = query.join(
                models.CandidateSearch,
                models.Candidate.candidate_id == models.CandidateSearch.id,
            ).distinct()

        if kwargs.get('cycle'):
            query = query.filter(models.Candidate.cycles.overlap(kwargs['cycle']))
        if kwargs.get('election_year'):
            query = query.filter(models.Candidate.election_years.overlap(kwargs['election_year']))

        return query


@doc(
    tags=['candidate'],
    description=docs.CANDIDATE_SEARCH,
)
class CandidateSearch(CandidateList):

    schema = schemas.CandidateSearchSchema
    page_schema = schemas.CandidateSearchPageSchema
    query_options = [sa.orm.subqueryload(models.Candidate.principal_committees)]


@doc(
    tags=['candidate'],
    description=docs.CANDIDATE_DETAIL,
    params={
        'candidate_id': {'description': docs.CANDIDATE_ID},
        'committee_id': {'description': docs.COMMITTEE_ID},
    },
)
class CandidateView(ApiResource):

    model = models.CandidateDetail
    schema = schemas.CandidateDetailSchema
    page_schema = schemas.CandidateDetailPageSchema
    filter_multi_fields = filter_multi_fields(models.CandidateDetail)
    # filter_match_fields = filter_match_fields(models.CandidateDetail)

    @property
    def args(self):
        return utils.extend(
            args.paging,
            args.candidate_detail,
            args.make_sort_args(
                default='name',
                validator=args.IndexValidator(self.model),
            ),
        )

    def build_query(self, candidate_id=None, committee_id=None, **kwargs):
        query = super().build_query(**kwargs)

        if candidate_id is not None:
            query = query.filter_by(candidate_id=candidate_id)

        if committee_id is not None:
            query = query.join(
                models.CandidateCommitteeLink
            ).filter(
                models.CandidateCommitteeLink.committee_id == committee_id
            ).distinct()

        if kwargs.get('cycle'):
            query = query.filter(models.CandidateDetail.cycles.overlap(kwargs['cycle']))
        if kwargs.get('election_year'):
            query = query.filter(models.Candidate.election_years.overlap(kwargs['election_year']))

        return query


@doc(
    tags=['candidate'],
    description=docs.CANDIDATE_HISTORY,
    params={
        'candidate_id': {'description': docs.CANDIDATE_ID},
        'committee_id': {'description': docs.COMMITTEE_ID},
        'cycle': {'description': docs.CANDIDATE_CYCLE},
    },
)
class CandidateHistoryView(ApiResource):

    model = models.CandidateHistory
    schema = schemas.CandidateHistorySchema
    page_schema = schemas.CandidateHistoryPageSchema

    @property
    def args(self):
        return utils.extend(
            args.paging,
            args.candidate_history,
            args.make_sort_args(
                default='-two_year_period',
                validator=args.IndexValidator(self.model),
            ),
        )

    def build_query(self, candidate_id=None, committee_id=None, cycle=None, **kwargs):
        query = models.CandidateHistory.query

        if candidate_id:
            query = query.filter(models.CandidateHistory.candidate_id == candidate_id)

        if committee_id:
            query = query.join(
                models.CandidateCommitteeLink,
                models.CandidateCommitteeLink.candidate_id == models.CandidateHistory.candidate_id,
            ).filter(
                models.CandidateCommitteeLink.committee_id == committee_id
            ).distinct()

        if cycle:
            query = (
                self._filter_elections(query, cycle)
                if kwargs.get('election_full')
                else query.filter(models.CandidateHistory.two_year_period == cycle)
            )

        return query

    def _filter_elections(self, query, cycle):
        """Round up to the next election including `cycle`."""
        return query.join(
            models.CandidateElection,
            sa.and_(
                models.CandidateHistory.candidate_id == models.CandidateElection.candidate_id,
                models.CandidateHistory.two_year_period <= models.CandidateElection.cand_election_year,
                models.CandidateHistory.two_year_period > models.CandidateElection.prev_election_year,
            ),
        ).filter(
            cycle <= models.CandidateElection.cand_election_year,
            cycle > models.CandidateElection.prev_election_year,
        ).order_by(
            models.CandidateHistory.candidate_id,
            sa.desc(models.CandidateHistory.two_year_period),
        ).distinct(
            models.CandidateHistory.candidate_id,
        )
